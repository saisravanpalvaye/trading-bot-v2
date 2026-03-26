"""
alert.py — Reads signals.json. Sends Telegram alert.
Auto-logs every signal as a paper trade. Never silent.
If no signals: sends STAY IN CASH message.
If error in signals.json: sends the error so you know something broke.
"""
import json
import csv
import os
import sys
from datetime import datetime, timezone, timedelta
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    SIGNALS_FILE, PAPER_TRADES_FILE, CAPITAL,
    SIZE_STRONG_BUY, SIZE_BUY, SIZE_WATCH,
)

IST = timezone(timedelta(hours=5, minutes=30))

PAPER_FIELDS = [
    "id", "date", "ticker", "setup_type", "conf_label", "conf_score",
    "entry", "sl", "target", "rr", "qty", "capital",
    "hold_days", "ev_pct", "reason",
    "status",        # open / closed / expired
    "exit_date", "exit_price", "exit_reason",
    "pnl", "result", "days_held",
]


# ── Telegram helpers ───────────────────────────────────────

def _send(text):
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

def _conf_tag(label):
    return {
        "STRONG BUY": "★ STRONG BUY",
        "BUY":        "✦ BUY",
        "WATCH":      "◎ WATCH",
    }.get(label, label)

def _build_pick_block(p, rank, total):
    """Build one pick block for the alert message."""
    entry  = float(p["entry"])
    sl     = float(p["sl"])
    tgt    = float(p["target"])
    qty    = int(p["qty"])
    cap    = float(p["capital"])
    rr     = float(p["rr"])
    pct_up = round((tgt - entry) / entry * 100, 1)
    pct_dn = round((entry - sl)  / entry * 100, 1)
    pnl_up = round((tgt - entry) * qty)
    pnl_dn = round((entry - sl)  * qty)
    label  = p["conf_label"]
    score  = p["conf_score"]

    lines = []
    lines.append(f"{'─'*34}")
    lines.append(f"{_conf_tag(label)}  #{rank} of {total}  [{score}/6]")
    lines.append(f"")
    lines.append(f"<b>{p['name']}</b>  [{p['sector']}]")
    lines.append(f"{p['setup_display']}")
    lines.append(f"")
    lines.append(f"Entry   <b>Rs {entry:,.2f}</b>   at open")
    lines.append(f"Target  Rs {tgt:,.2f}   +{pct_up}%  (+Rs {pnl_up:,})")
    lines.append(f"SL      Rs {sl:,.2f}   -{pct_dn}%  (-Rs {pnl_dn:,})")
    lines.append(f"")

    size_note = "  ⚠️ 50% size — VIX elevated" if p.get("vix_reduced") else ""
    lines.append(f"Size    Rs {cap:,.0f}  ({qty} shares){size_note}")
    lines.append(f"Hold    up to {p['hold_days']} trading days")
    lines.append(f"")
    lines.append(f"<i>{p['reason']}</i>")

    if p.get("gap_down"):
        lines.append(f"⚠️  Gap down expected — confirm at 9:30 AM first")

    return "\n".join(lines)


def build_alert_message(payload, is_reminder=False):
    """Build the full Telegram message from signals.json payload."""
    now      = datetime.now(IST)
    # Use trade_date from signals.json — brain already calculated the correct
    # next market day when it ran. This avoids midnight rollover issues where
    # alert.py runs just after midnight and date.today() is already next day.
    signal_trade_date = payload.get("date", "")
    if signal_trade_date:
        try:
            from datetime import date as _date
            td = datetime.strptime(signal_trade_date, "%Y-%m-%d")
            mkt_label = td.strftime("%a %d %b %Y").upper()
        except Exception:
            mkt_label = signal_trade_date
    else:
        mkt_label = "NEXT MARKET DAY"
    date_str = (mkt_label +
                " · " + now.strftime("%I:%M %p IST").upper() +
                "  (for tomorrow\'s open)")
    regime   = payload.get("regime", "UNKNOWN")
    rdesc    = payload.get("regime_desc", "")
    rsi      = payload.get("nifty_rsi")
    vix      = payload.get("vix_val")
    picks    = payload.get("picks", [])
    error    = payload.get("error")

    lines = []

    # Header
    if is_reminder:
        lines.append("⏰ <b>REMINDER — market opens in 75 minutes</b>")
        lines.append("Signals from last night. Still valid unless major news.")
        lines.append("")

    lines.append(f"<b>TRADING SIGNALS</b>")
    lines.append(f"<i>{date_str}</i>")

    # Regime bar
    icon  = _regime_icon(regime)
    rsi_s = f"Nifty RSI {rsi}" if rsi else "RSI --"
    vix_s = f"VIX {vix}"       if vix else "VIX --"
    lines.append(f"{icon} {regime}  ·  {rsi_s}  ·  {vix_s}")
    lines.append(f"<i>{rdesc}</i>")

    # Error state
    if error:
        lines.append(f"")
        lines.append(f"❌ Bot encountered an error:")
        lines.append(f"<code>{error[:200]}</code>")
        lines.append(f"Check GitHub Actions logs.")
        return "\n".join(lines)

    # No market day
    if not payload.get("market_open", True):
        lines.append(f"")
        lines.append(f"Market closed today — no signals.")
        return "\n".join(lines)

    # Capital summary
    total_deployable = round(CAPITAL * 0.60)
    lines.append(f"{'─'*34}")
    rsi_str = f"{rsi}" if rsi else "--"
    lines.append(f"Scanning complete  ·  {len(picks)} signal(s) found")
    lines.append(f"Max deployable: Rs {total_deployable:,}")

    # No picks
    if not picks:
        lines.append(f"")
        lines.append(f"<b>⛔ STAY IN CASH TODAY</b>")
        if regime == "HIGH_VIX":
            lines.append(f"VIX {vix} above danger threshold ({22}).")
            lines.append(f"No new positions. Protect capital.")
        else:
            lines.append(f"No setups qualify today. Patience is a position.")
        lines.append(f"{'─'*34}")
        lines.append(f"<i>Not SEBI advice · Your decision</i>")
        return "\n".join(lines)

    # Individual picks
    for i, p in enumerate(picks, 1):
        lines.append(_build_pick_block(p, i, len(picks)))

    # Capital summary at bottom
    strong_picks = [p for p in picks if p["conf_label"] == "STRONG BUY"]
    buy_picks    = [p for p in picks if p["conf_label"] == "BUY"]
    total_if_all = sum(float(p["capital"]) for p in picks)

    lines.append(f"{'─'*34}")
    lines.append(f"If you take all: Rs {total_if_all:,.0f} deployed")
    lines.append(f"Rs {CAPITAL - total_if_all:,.0f} remains free")
    lines.append(f"{'─'*34}")
    lines.append(f"<i>Paper trading · Not SEBI advice · Your decision</i>")

    return "\n".join(lines)


# ── Paper trade logger ─────────────────────────────────────

def _next_paper_id():
    """Generate next PT-XXX id."""
    if not os.path.exists(PAPER_TRADES_FILE):
        return "PT-001"
    with open(PAPER_TRADES_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return "PT-001"
    ids = []
    for r in rows:
        try:
            ids.append(int(r.get("id", "PT-000").replace("PT-", "")))
        except ValueError:
            pass
    return f"PT-{max(ids) + 1:03d}"


def log_paper_trades(picks, signal_date):
    """
    Auto-log every signal as a paper trade.
    Called automatically — you never need to add rows manually.
    """
    if not picks:
        return

    exists = os.path.exists(PAPER_TRADES_FILE)

    with open(PAPER_TRADES_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PAPER_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()

        for p in picks:
            tid = _next_paper_id()
            writer.writerow({
                "id":          tid,
                "date":        signal_date,
                "ticker":      p["ticker"],
                "setup_type":  p["setup_type"],
                "conf_label":  p["conf_label"],
                "conf_score":  p["conf_score"],
                "entry":       p["entry"],
                "sl":          p["sl"],
                "target":      p["target"],
                "rr":          p["rr"],
                "qty":         p["qty"],
                "capital":     p["capital"],
                "hold_days":   p["hold_days"],
                "ev_pct":      p["ev_pct"],
                "reason":      p["reason"],
                "status":      "open",
                "exit_date":   "",
                "exit_price":  "",
                "exit_reason": "",
                "pnl":         "",
                "result":      "",
                "days_held":   "",
            })
            print(f"  Paper trade logged: {tid} — {p['name']} {p['conf_label']}")


# ── Main ───────────────────────────────────────────────────

def run(is_reminder=False):
    print(f"\n{'='*52}")
    mode = "REMINDER" if is_reminder else "ALERT"
    print(f"  {mode}  {datetime.now(IST).strftime('%d %b %Y  %H:%M IST')}")
    print(f"{'='*52}\n")

    # Load signals.json
    try:
        with open(SIGNALS_FILE) as f:
            payload = json.load(f)
    except FileNotFoundError:
        payload = {
            "date": "", "market_open": True, "regime": "UNKNOWN",
            "regime_desc": "signals.json not found — brain.py may have failed",
            "nifty_rsi": None, "vix_val": None, "vix_action": "normal",
            "picks": [],
            "error": "signals.json missing. Check GitHub Actions logs.",
        }
    except Exception as e:
        payload = {
            "date": "", "market_open": True, "regime": "UNKNOWN",
            "regime_desc": "Could not read signals.json",
            "nifty_rsi": None, "vix_val": None, "vix_action": "normal",
            "picks": [],
            "error": str(e),
        }

    # Build and send message
    msg = build_alert_message(payload, is_reminder=is_reminder)
    _send(msg)

    # Auto-log paper trades (only on first alert, not reminder)
    if not is_reminder and payload.get("picks"):
        print("\n  Auto-logging paper trades...")
        log_paper_trades(payload["picks"], payload.get("date", ""))

    print("\n  Done.")


if __name__ == "__main__":
    reminder = "--reminder" in sys.argv
    run(is_reminder=reminder)
