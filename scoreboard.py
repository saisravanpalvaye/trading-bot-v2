"""
scoreboard.py — Runs at 3:35 PM IST every market day.
Checks every open paper trade against live prices.
Closes trades that hit SL, target, or max hold days.
Sends evening P&L summary to Telegram.
Completely independent — works even if brain.py failed today.
"""
import csv
import os
import sys
import json
from datetime import datetime, timezone, timedelta, date
import yfinance as yf
import pandas as pd
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    PAPER_TRADES_FILE, CAPITAL, MAX_HOLD_DAYS,
    NSE_HOLIDAYS_2026,
)

IST = timezone(timedelta(hours=5, minutes=30))

PAPER_FIELDS = [
    "id", "date", "ticker", "setup_type", "conf_label", "conf_score",
    "entry", "sl", "target", "rr", "qty", "capital",
    "hold_days", "ev_pct", "reason",
    "status", "exit_date", "exit_price", "exit_reason",
    "pnl", "result", "days_held",
]


# ── Helpers ────────────────────────────────────────────────

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
            print("  Scoreboard sent.")
            return True
        print(f"  Telegram error: {r.status_code}")
        return False
    except Exception as e:
        print(f"  Telegram failed: {e}")
        return False


def _load_trades():
    if not os.path.exists(PAPER_TRADES_FILE):
        return []
    with open(PAPER_TRADES_FILE, newline="") as f:
        return list(csv.DictReader(f))


def _save_trades(trades):
    with open(PAPER_TRADES_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PAPER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)


def _count_trading_days(start_str, end_date):
    """Count actual NSE trading days between entry date and today."""
    try:
        start = date.fromisoformat(start_str)
        count = 0
        cur   = start
        while cur < end_date:
            if cur.weekday() < 5 and cur.isoformat() not in NSE_HOLIDAYS_2026:
                count += 1
            cur = date.fromordinal(cur.toordinal() + 1)
        return count
    except Exception:
        return 0


def _fetch_price(ticker):
    """Get today's high, low, close for a ticker."""
    try:
        raw = yf.download(ticker, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        if raw is None or len(raw) == 0:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        row = raw.iloc[-1]
        return {
            "high":  float(row["High"]),
            "low":   float(row["Low"]),
            "close": float(row["Close"]),
            "date":  raw.index[-1].strftime("%Y-%m-%d"),
        }
    except Exception:
        return None


# ── Monitor open trades ────────────────────────────────────

def monitor_and_close():
    """
    Check all open paper trades.
    Close any that hit SL, target, or max hold days.
    Returns (closed_today, all_trades).
    """
    trades  = _load_trades()
    open_t  = [t for t in trades if t.get("status") == "open"]
    today   = date.today()
    closed_today = []

    if not open_t:
        print("  No open paper trades.")
        return [], trades

    print(f"  Checking {len(open_t)} open trades...")

    for t in open_t:
        ticker  = t["ticker"]
        entry   = float(t["entry"])
        sl      = float(t["sl"])
        target  = float(t["target"])
        qty     = int(float(t.get("qty", 0)))
        days    = _count_trading_days(t.get("date", ""), today)

        price = _fetch_price(ticker)
        if price is None:
            print(f"  Could not fetch {ticker} — skipping")
            continue

        exit_reason = None
        exit_price  = None

        if price["low"] <= sl:
            exit_reason = "SL"
            exit_price  = sl
        elif price["high"] >= target:
            exit_reason = "TARGET"
            exit_price  = target
        elif days >= MAX_HOLD_DAYS:
            exit_reason = "DAY_CAP"
            exit_price  = price["close"]

        if exit_reason:
            pnl    = round((exit_price - entry) * qty, 2)
            result = "WIN" if exit_price > entry else "LOSS"
            t.update({
                "status":      "closed",
                "exit_date":   price["date"],
                "exit_price":  round(exit_price, 2),
                "exit_reason": exit_reason,
                "pnl":         pnl,
                "result":      result,
                "days_held":   days,
            })
            closed_today.append(t)
            icon = "✅" if result == "WIN" else "❌"
            print(f"  {icon} CLOSED {t['id']} {ticker.replace('.NS','')} "
                  f"{exit_reason} Rs{pnl:+,.0f}")

    _save_trades(trades)
    return closed_today, trades


# ── Performance stats ──────────────────────────────────────

def _calc_stats(trades):
    """Calculate all performance metrics from trade history."""
    closed = [t for t in trades if t.get("status") == "closed"]
    open_t = [t for t in trades if t.get("status") == "open"]

    if not closed:
        return None, open_t

    wins   = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]
    pnls   = [float(t.get("pnl", 0)) for t in closed]
    total  = sum(pnls)
    wr     = len(wins) / len(closed) * 100 if closed else 0

    # Profit factor
    win_sum  = sum(float(t["pnl"]) for t in wins)
    loss_sum = abs(sum(float(t["pnl"]) for t in losses))
    pf       = round(win_sum / loss_sum, 2) if loss_sum > 0 else 0

    # Max drawdown
    equity = CAPITAL
    peak   = CAPITAL
    mdd    = 0
    for p in pnls:
        equity += p
        peak    = max(peak, equity)
        mdd     = max(mdd, (peak - equity) / peak * 100)

    # This week and this month
    today     = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    week_pnl  = sum(
        float(t.get("pnl", 0)) for t in closed
        if t.get("exit_date", "") >= week_start.isoformat()
    )
    month_pnl = sum(
        float(t.get("pnl", 0)) for t in closed
        if t.get("exit_date", "") >= month_start.isoformat()
    )

    # By confidence label
    by_conf = {}
    for label in ["STRONG BUY", "BUY", "WATCH"]:
        g = [t for t in closed if t.get("conf_label") == label]
        if g:
            w = len([t for t in g if t.get("result") == "WIN"])
            by_conf[label] = {
                "n":    len(g),
                "wr":   round(w / len(g) * 100, 1),
                "pnl":  round(sum(float(t.get("pnl", 0)) for t in g), 0),
            }

    return {
        "total_closed": len(closed),
        "total_open":   len(open_t),
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(wr, 1),
        "total_pnl":    round(total, 0),
        "week_pnl":     round(week_pnl, 0),
        "month_pnl":    round(month_pnl, 0),
        "profit_factor":pf,
        "max_dd":       round(mdd, 1),
        "by_conf":      by_conf,
    }, open_t


# ── Message builder ────────────────────────────────────────

def _get_live_pnl(open_trades):
    """Fetch current price for each open trade for live P&L."""
    live = []
    for t in open_trades:
        price = _fetch_price(t["ticker"])
        if price:
            entry = float(t["entry"])
            qty   = int(float(t.get("qty", 0)))
            ltp   = price["close"]
            pnl   = round((ltp - entry) * qty, 0)
            live.append({**t, "ltp": ltp, "live_pnl": pnl})
        else:
            live.append({**t, "ltp": None, "live_pnl": None})
    return live


def build_scoreboard_message(closed_today, all_trades):
    """Build the evening scoreboard Telegram message."""
    now      = datetime.now(IST)
    date_str = now.strftime("%a %d %b · %I:%M %p IST").upper()
    stats, open_t = _calc_stats(all_trades)

    lines = []
    lines.append(f"<b>SCOREBOARD</b>")
    lines.append(f"<i>{date_str}</i>")
    lines.append(f"{'─'*32}")

    # Closed today
    if closed_today:
        lines.append(f"<b>Closed today ({len(closed_today)})</b>")
        for t in closed_today:
            pnl  = float(t.get("pnl", 0))
            icon = "✅" if t.get("result") == "WIN" else "❌"
            rsn  = t.get("exit_reason", "")
            nm   = t.get("ticker", "").replace(".NS", "")
            cl   = t.get("conf_label", "")
            lines.append(
                f"  {icon} {nm}  {rsn}  "
                f"<b>Rs {pnl:+,.0f}</b>  [{cl}]"
            )
    else:
        lines.append("No trades closed today.")

    # Open trades with live P&L
    if open_t:
        lines.append(f"{'─'*32}")
        lines.append(f"<b>Open trades ({len(open_t)})</b>")
        live_open = _get_live_pnl(open_t)
        for t in live_open:
            nm    = t.get("ticker", "").replace(".NS", "")
            entry = float(t.get("entry", 0))
            ltp   = t.get("ltp")
            lpnl  = t.get("live_pnl")
            today_val = date.today()
            days  = _count_trading_days(t.get("date", ""), today_val)
            if ltp and lpnl is not None:
                icon = "↑" if lpnl >= 0 else "↓"
                lines.append(
                    f"  {nm}  Day {days}  "
                    f"entry {entry:,.0f} → now {ltp:,.0f}  "
                    f"{icon} Rs {lpnl:+,.0f}"
                )
            else:
                lines.append(f"  {nm}  Day {days}  entry {entry:,.0f}  (price unavailable)")

    # Running stats
    if stats:
        lines.append(f"{'─'*32}")
        pnl_icon = "▲" if stats["total_pnl"] >= 0 else "▼"
        lines.append(f"<b>This week</b>   Rs {stats['week_pnl']:+,.0f}")
        lines.append(f"<b>This month</b>  Rs {stats['month_pnl']:+,.0f}")
        lines.append(f"<b>All time</b>    Rs {stats['total_pnl']:+,.0f}")
        lines.append(f"{'─'*32}")
        lines.append(
            f"Win rate  {stats['win_rate']:.0f}%  "
            f"({stats['wins']}W / {stats['losses']}L)"
        )
        lines.append(f"Profit factor  {stats['profit_factor']:.2f}x")
        lines.append(f"Max drawdown   {stats['max_dd']:.1f}%")

        # By confidence
        if stats["by_conf"]:
            lines.append(f"{'─'*32}")
            lines.append("<b>By signal type</b>")
            for label, s in stats["by_conf"].items():
                lines.append(
                    f"  {label:12s}  {s['n']} trades  "
                    f"WR {s['wr']:.0f}%  "
                    f"Rs {s['pnl']:+,.0f}"
                )

        # Milestone message
        n = stats["total_closed"]
        if n in (10, 20, 30, 50):
            lines.append(f"{'─'*32}")
            if n == 30:
                lines.append(f"🎯 <b>30 trades complete!</b>")
                lines.append(f"Time to review: is the win rate above 55%?")
                lines.append(f"If yes → consider going live with real money.")
            else:
                lines.append(f"🎯 {n} trades complete. Keep going.")
    else:
        lines.append(f"{'─'*32}")
        lines.append("No closed trades yet. Paper trading in progress.")

    lines.append(f"{'─'*32}")
    lines.append("<i>Paper trading · Not SEBI advice</i>")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────

def run():
    now = datetime.now(IST)
    print(f"\n{'='*52}")
    print(f"  SCOREBOARD  {now.strftime('%d %b %Y  %H:%M IST')}")
    print(f"{'='*52}\n")

    print("[1/2] Monitoring open trades...")
    closed_today, all_trades = monitor_and_close()

    print("\n[2/2] Sending scoreboard...")
    msg = build_scoreboard_message(closed_today, all_trades)
    _send(msg)

    stats, _ = _calc_stats(all_trades)
    if stats:
        print(f"\n  Summary: {stats['total_closed']} closed | "
              f"{stats['total_open']} open | "
              f"WR {stats['win_rate']:.0f}% | "
              f"Month Rs{stats['month_pnl']:+,.0f}")

    print("\n  Done.")


if __name__ == "__main__":
    run()
