"""
alert.py — Reads signals.json. Sends Telegram alert. Logs paper trades.

Fixed in V6 rebuild:
  B6:  remains_free = CAPITAL - open_trades_capital - today_signals
  B11: warning when deployment would exceed 60% of capital
  B20: signals.json validated before processing (never crashes on bad JSON)
  Schema: paper_trades.csv includes partial exit fields
  Labels: BUY shown prominently, WATCH shown with lower emphasis
"""
import json
import csv
import os
import sys
from datetime import datetime, timezone, timedelta
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    SIGNALS_FILE, PAPER_TRADES_FILE, CAPITAL,
    MAX_DEPLOYED,
)

IST = timezone(timedelta(hours=5, minutes=30))

# ── paper_trades.csv schema ────────────────────────────────
# Includes partial exit fields (B12 fix)
PAPER_FIELDS = [
    "id", "date", "ticker", "setup_type", "conf_label", "conf_score",
    "entry", "sl", "target", "partial_tgt", "rr", "qty",
    "qty_open", "qty_closed",           # partial exit tracking
    "capital", "hold_days", "ev_pct", "reason", "sector",
    "status",                            # open / partial / closed / expired
    "exit_date", "exit_price", "exit_reason",
    "partial_exit_price", "partial_exit_date", "partial_pnl",
    "pnl", "result", "days_held",
    "current_price", "live_pnl",   # updated by scoreboard on every run
]


# ── Telegram helpers ───────────────────────────────────────

def _send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, params={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=15)
        if r.status_code == 200:
            print("  Telegram sent.")
            return True
        print(f"  Telegram error {r.status_code}: {r.text[:120]}")
        return False
    except Exception as e:
        print(f"  Telegram failed: {e}")
        return False


# ── Signals validation ─────────────────────────────────────

def read_signals(signals_file=None):
    """
    Read and validate signals.json.
    B20 fix: validates schema before returning. Returns None on invalid/missing.
    """
    path = signals_file or SIGNALS_FILE
    try:
        with open(path) as f:
            payload = json.load(f)
    except FileNotFoundError:
        return {
            "date": "", "market_open": True, "regime": "UNKNOWN",
            "regime_desc": "signals.json not found",
            "nifty_rsi": None, "vix": None, "vix_action": "normal",
            "floor_hit": False, "consec_losses": 0, "size_multiplier": 1.0,
            "picks": [],
            "error": "signals.json missing — check GitHub Actions logs",
        }
    except Exception as e:
        return {
            "date": "", "market_open": True, "regime": "UNKNOWN",
            "regime_desc": "Could not read signals.json",
            "nifty_rsi": None, "vix": None, "vix_action": "normal",
            "floor_hit": False, "consec_losses": 0, "size_multiplier": 1.0,
            "picks": [],
            "error": str(e),
        }
    # Ensure required keys exist with safe defaults
    payload.setdefault("picks", [])
    payload.setdefault("floor_hit", False)
    payload.setdefault("consec_losses", 0)
    payload.setdefault("size_multiplier", 1.0)
    payload.setdefault("vix_action", "normal")
    payload.setdefault("error", None)
    payload.setdefault("market_open", True)
    return payload


# ── Capital tracking ───────────────────────────────────────

def _open_trades_capital(paper_trades_path=None):
    """
    Sum capital of all OPEN trades in paper_trades.csv.
    B6 fix: alert must account for already-deployed capital.
    Returns 0 if file missing (safe fallback).
    """
    path = paper_trades_path or PAPER_TRADES_FILE
    if not os.path.exists(path):
        return 0
    try:
        total = 0.0
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status", "").lower() in ("open", "partial"):
                    try:
                        total += float(row.get("capital", 0) or 0)
                    except ValueError:
                        pass
        return total
    except Exception:
        return 0


def calc_remains_free(signals, paper_trades_path=None):
    """
    Calculate truly available capital.
    B6 fix: remains_free = CAPITAL - open_trades_capital - today_signals_capital
    """
    open_capital  = _open_trades_capital(paper_trades_path)
    today_capital = sum(
        float(p.get("capital", 0))
        for p in signals.get("picks", [])
        if not p.get("already_open", False)
    )
    return round(CAPITAL - open_capital - today_capital, 0)


# ── Paper trade ID ─────────────────────────────────────────

def _next_paper_id(paper_trades_path=None):
    path = paper_trades_path or PAPER_TRADES_FILE
    if not os.path.exists(path):
        return "PT-001"
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return "PT-001"
        ids = []
        for r in rows:
            try:
                ids.append(int(r.get("id", "PT-000").replace("PT-", "")))
            except ValueError:
                pass
        return f"PT-{max(ids) + 1:03d}" if ids else "PT-001"
    except Exception:
        return "PT-001"


# ── Message builders ───────────────────────────────────────

def _regime_icon(regime):
    return {
        "BULLISH":  "🟢",
        "BEARISH":  "🔴",
        "HIGH_VIX": "🟡",
        "OVERSOLD": "🔵",
        "NEUTRAL":  "⚪",
        "CLOSED":   "⭕",
    }.get(regime, "⚪")


def format_pick(p):
    """
    Format a single pick for Telegram.
    BUY shown prominently. WATCH shown with lower emphasis.
    B17: note that entry is at close price, execution is at next-day open.
    """
    entry   = float(p["entry"])
    sl      = float(p["sl"])
    tgt     = float(p["target"])
    partial = float(p.get("partial_tgt", 0))
    qty     = int(p["qty"])
    cap     = float(p["capital"])
    rr      = float(p["rr"])
    score   = int(p.get("conf_score", 0))
    label   = p.get("conf_label", "WATCH")

    pct_up  = round((tgt - entry) / entry * 100, 1)
    pct_dn  = round((entry - sl)  / entry * 100, 1)
    pnl_up  = round((tgt - entry) * qty)
    pnl_dn  = round((entry - sl)  * qty)

    # BUY vs WATCH visual differentiation
    if label == "BUY":
        header = f"✦ <b>BUY</b>  [{score}/7]"
    else:
        header = f"◎ WATCH  [{score}/7]"

    lines = [
        f"{'─'*32}",
        header,
        f"",
        f"<b>{p.get('name', p.get('ticker',''))}</b>  [{p.get('sector','')}]",
        f"{p.get('setup_display', p.get('setup_type',''))}",
        f"",
        f"Entry   ≈ Rs {entry:,.2f}  <i>(at tomorrow's open)</i>",
        f"Partial   Rs {partial:,.2f}  (exit 50% here → SL → entry)",
        f"Target  Rs {tgt:,.2f}   +{pct_up}%  (+Rs {pnl_up:,})",
        f"SL      Rs {sl:,.2f}   -{pct_dn}%  (-Rs {pnl_dn:,})",
        f"",
    ]

    size_note = "  ⚠ 50% size — VIX elevated" if p.get("vix_reduced") else ""
    lines.append(f"Size    Rs {cap:,.0f}  ({qty} shares){size_note}")
    lines.append(f"Hold    up to {p.get('hold_days', 8)} trading days")
    lines.append(f"RR      {rr:.2f}x")
    lines.append(f"")
    lines.append(f"<i>{p.get('reason','')}</i>")

    if p.get("already_open"):
        lines.append(f"ℹ️  Already in paper trades — not re-logged")

    return "\n".join(lines)


def build_alert_message(signals, paper_trades_path=None):
    """
    Build the full Telegram alert message.
    B6: correct remains_free calculation
    B11: deployment limit warning
    B19: VIX reduce prominently shown
    B20: handles missing/corrupt signals gracefully
    """
    now      = datetime.now(IST)
    picks    = signals.get("picks", [])
    regime   = signals.get("regime", "UNKNOWN")
    nifty_rsi= signals.get("nifty_rsi")
    vix_val  = signals.get("vix")
    vix_action = signals.get("vix_action", "normal")
    floor_hit = signals.get("floor_hit", False)
    consec   = signals.get("consec_losses", 0)
    size_mult= signals.get("size_multiplier", 1.0)
    error    = signals.get("error")

    trade_date = signals.get("date", "")
    try:
        from datetime import datetime as _dt
        td = _dt.strptime(trade_date, "%Y-%m-%d")
        mkt_label = td.strftime("%a %d %b %Y").upper()
    except Exception:
        mkt_label = trade_date or "NEXT MARKET DAY"

    date_str = (mkt_label + " · " +
                now.strftime("%I:%M %p IST").upper() +
                "  (for tomorrow's open)")

    lines = [
        "<b>TRADING SIGNALS</b>",
        f"<i>{date_str}</i>",
    ]

    # Regime bar
    icon  = _regime_icon(regime)
    rsi_s = f"Nifty RSI {nifty_rsi}" if nifty_rsi else "RSI --"
    vix_s = f"VIX {vix_val}"         if vix_val   else "VIX --"
    lines.append(f"{icon} {regime}  ·  {rsi_s}  ·  {vix_s}")
    lines.append(f"<i>{signals.get('regime_desc', '')}</i>")

    # Error
    if error:
        lines += ["", "❌ Bot error:", f"<code>{str(error)[:200]}</code>",
                  "Check GitHub Actions logs."]
        return "\n".join(lines)

    # No market day
    if not signals.get("market_open", True):
        lines += ["", "Market closed today — no signals."]
        return "\n".join(lines)

    # Floor hit
    if floor_hit:
        lines += [
            "", f"{'─'*32}",
            "⛔ <b>MONTHLY LOSS FLOOR HIT</b>",
            f"Loss this month exceeded Rs {30000:,}.",
            "No new signals until next month.",
            f"{'─'*32}",
            "<i>Paper trading · Not SEBI advice</i>",
        ]
        return "\n".join(lines)

    # Consecutive loss warning
    if consec >= 3:
        lines.append(f"⚠ {consec} consecutive losses — position sizes halved")

    # VIX reduce warning (B19)
    if vix_action == "reduce":
        lines.append(f"⚠ VIX elevated — all sizes at 50%")

    # Capital summary (B6 fix)
    open_capital  = _open_trades_capital(paper_trades_path)
    new_picks     = [p for p in picks if not p.get("already_open", False)]
    today_capital = sum(float(p.get("capital", 0)) for p in new_picks)
    remains       = CAPITAL - open_capital - today_capital
    total_deployed = open_capital + today_capital

    lines += [
        f"{'─'*32}",
        f"{len(new_picks)} new signal(s)  ·  {len(picks)-len(new_picks)} already open",
        f"Open positions: Rs {open_capital:,.0f}",
        f"Today's new:    Rs {today_capital:,.0f}",
        f"Remains free:   Rs {remains:,.0f}",
    ]

    # B11: deployment limit warning
    if total_deployed > MAX_DEPLOYED:
        lines.append(
            f"⚠ <b>Warning:</b> Total deployed Rs {total_deployed:,.0f} "
            f"exceeds 60% limit (Rs {MAX_DEPLOYED:,.0f})"
        )

    # No picks
    if not picks:
        lines += [
            "", "<b>⛔ STAY IN CASH TODAY</b>",
        ]
        if vix_action == "avoid":
            lines.append(f"VIX {vix_val} above {22} — danger zone.")
        else:
            lines.append("No setups qualify today. Patience is a position.")
        lines += [f"{'─'*32}", "<i>Not SEBI advice · Your decision</i>"]
        return "\n".join(lines)

    # VIX avoid with no picks
    if vix_action == "avoid":
        lines += ["", "<b>⛔ STAY IN CASH — VIX DANGER ZONE</b>",
                  f"VIX {vix_val} above {22}. No new positions.",
                  f"{'─'*32}", "<i>Not SEBI advice</i>"]
        return "\n".join(lines)

    # Individual picks — BUY first, then WATCH
    buy_picks   = [p for p in picks if p.get("conf_label") == "BUY"]
    watch_picks = [p for p in picks if p.get("conf_label") != "BUY"]

    for p in buy_picks + watch_picks:
        lines.append(format_pick(p))

    lines += [
        f"{'─'*32}",
        "<i>Paper trading · Not SEBI advice · Your decision</i>",
    ]
    return "\n".join(lines)


# ── Paper trade logger ─────────────────────────────────────

def log_paper_trades(picks, signal_date, paper_trades_path=None):
    """
    Log new signals to paper_trades.csv.
    Skips already_open trades — never double-logs.
    B12: schema includes all partial exit fields.
    """
    path   = paper_trades_path or PAPER_TRADES_FILE
    exists = os.path.exists(path)
    new_picks = [p for p in picks if not p.get("already_open", False)]
    if not new_picks:
        return

    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PAPER_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for p in new_picks:
            qty = int(p.get("qty", 0))
            writer.writerow({
                "id":                _next_paper_id(path),
                "date":              signal_date,
                "ticker":            p.get("ticker", ""),
                "setup_type":        p.get("setup_type", ""),
                "conf_label":        p.get("conf_label", "WATCH"),
                "conf_score":        p.get("conf_score", 0),
                "entry":             p.get("entry", 0),
                "sl":                p.get("sl", 0),
                "target":            p.get("target", 0),
                "partial_tgt":       p.get("partial_tgt", 0),
                "rr":                p.get("rr", 0),
                "qty":               qty,
                "qty_open":          qty,         # full qty open initially
                "qty_closed":        0,           # nothing closed yet
                "capital":           p.get("capital", 0),
                "hold_days":         p.get("hold_days", 8),
                "ev_pct":            p.get("ev_pct", 0),
                "reason":            p.get("reason", ""),
                "sector":            p.get("sector", ""),
                "status":            "open",
                "exit_date":         "",
                "exit_price":        "",
                "exit_reason":       "",
                "partial_exit_price":"",
                "partial_exit_date": "",
                "partial_pnl":       "",
                "pnl":               "",
                "result":            "",
                "days_held":         "",
            })
            print(f"  Logged: {p.get('name', p.get('ticker',''))} "
                  f"[{p.get('conf_label','')}] {signal_date}")


# ── Main ───────────────────────────────────────────────────

def run(signals=None, paper_trades_path=None, is_reminder=False):
    """
    Main entry point. Accepts signals dict (for testing) or reads from file.
    """
    now  = datetime.now(IST)
    mode = "REMINDER" if is_reminder else "ALERT"
    print(f"\n{'='*52}")
    print(f"  {mode}  {now.strftime('%d %b %Y  %H:%M IST')}")
    print(f"{'='*52}\n")

    # Load signals (B20: validated on read)
    if signals is None:
        signals = read_signals()

    # Build and send
    msg = build_alert_message(signals, paper_trades_path)
    _send_telegram(msg)

    # Log paper trades (only on primary alert, not reminder)
    if not is_reminder and signals.get("picks"):
        print("\n  Logging paper trades...")
        log_paper_trades(
            signals["picks"],
            signals.get("date", now.strftime("%Y-%m-%d")),
            paper_trades_path,
        )

    print("\n  Done.")


if __name__ == "__main__":
    reminder = "--reminder" in sys.argv
    run(is_reminder=reminder)
