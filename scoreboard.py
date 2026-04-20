"""
scoreboard.py — Runs at 3:35 PM IST every market day.

Fixed in V6 rebuild:
  B12: paper_trades schema has partial fields
  B16: phantom trade validation (skips bad entry_date rows)
  B18: partial exit automation (triggers when HIGH >= partial_tgt)
  B21: SL uses LOW, target uses HIGH, partial uses HIGH (not close)
  trade_log.csv: writes all closed trades (enables monthly floor + consec checks)
"""
import csv
import os
import sys
from datetime import datetime, timezone, timedelta, date
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    PAPER_TRADES_FILE, TRADE_LOG_FILE, CAPITAL,
    HOLD_DAYS, NSE_HOLIDAYS_2026,
)

IST = timezone(timedelta(hours=5, minutes=30))

PAPER_FIELDS = [
    "id", "date", "ticker", "setup_type", "conf_label", "conf_score",
    "entry", "sl", "target", "partial_tgt", "rr", "qty",
    "qty_open", "qty_closed",
    "capital", "hold_days", "ev_pct", "reason", "sector",
    "status",
    "exit_date", "exit_price", "exit_reason",
    "partial_exit_price", "partial_exit_date", "partial_pnl",
    "pnl", "result", "days_held",
    "current_price", "live_pnl",   # updated by scoreboard on every run
]

TRADE_LOG_FIELDS = [
    "id", "date", "ticker", "setup_type", "conf_label",
    "entry", "exit_date", "exit_price", "exit_reason",
    "sl", "target", "qty", "capital", "pnl", "result", "days_held",
]


# ── Telegram ───────────────────────────────────────────────

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


# ── Trade I/O ──────────────────────────────────────────────

def load_open_trades(paper_trades_path=None):
    """
    Load OPEN trades from paper_trades.csv.
    B16 fix: validates entry_date format — skips phantom/bad rows.
    Returns list of valid open trade dicts.
    """
    path = paper_trades_path or PAPER_TRADES_FILE
    if not os.path.exists(path):
        return []
    valid = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                # B16: Skip invalid rows
                ticker     = row.get("ticker", "").strip()
                status     = row.get("status", "").strip().lower()
                entry_date = row.get("date", "").strip()

                if not ticker:
                    continue
                if status not in ("open", "partial"):
                    continue
                try:
                    date.fromisoformat(entry_date)
                except ValueError:
                    print(f"  [PHANTOM] Skipping {ticker}: bad date '{entry_date}'")
                    continue
                valid.append(dict(row))
    except Exception as e:
        print(f"  [LOAD] Error reading {path}: {e}")
    return valid


def _save_all_trades(trades, paper_trades_path=None):
    """Rewrite entire paper_trades.csv with all rows."""
    path = paper_trades_path or PAPER_TRADES_FILE
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PAPER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)


def _append_trade_log(closed_trade, trade_log_path=None):
    """
    Append one closed trade to trade_log.csv.
    Creates file and header if it doesn't exist yet.
    This enables brain.py's monthly floor and consecutive loss checks.
    """
    path   = trade_log_path or TRADE_LOG_FILE
    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=TRADE_LOG_FIELDS, extrasaction="ignore"
        )
        if not exists:
            writer.writeheader()
        writer.writerow({
            "id":          closed_trade.get("id", ""),
            "date":        closed_trade.get("date", ""),
            "ticker":      closed_trade.get("ticker", ""),
            "setup_type":  closed_trade.get("setup_type", ""),
            "conf_label":  closed_trade.get("conf_label", ""),
            "entry":       closed_trade.get("entry", ""),
            "exit_date":   closed_trade.get("exit_date", ""),
            "exit_price":  closed_trade.get("exit_price", ""),
            "exit_reason": closed_trade.get("exit_reason", ""),
            "sl":          closed_trade.get("sl", ""),
            "target":      closed_trade.get("target", ""),
            "qty":         closed_trade.get("qty", ""),
            "capital":     closed_trade.get("capital", ""),
            "pnl":         closed_trade.get("pnl", ""),
            "result":      closed_trade.get("result", ""),
            "days_held":   closed_trade.get("days_held", ""),
        })


# ── Trading day counter ────────────────────────────────────

def _count_trading_days(start_str, end_date):
    """Count actual NSE trading days from entry date to today (exclusive)."""
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


# ── Price fetch ────────────────────────────────────────────

def _fetch_price(ticker):
    """Get today's high, low, close for a ticker. Returns dict or None."""
    import yfinance as yf
    import pandas as pd
    try:
        raw = yf.download(
            ticker, period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )
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


# ── Exit detection (B21 fix) ───────────────────────────────

def check_sl_trigger(trade, price_bar):
    """
    SL triggered when LOW <= sl.
    B21: uses LOW not close for SL detection.
    """
    try:
        return float(price_bar["low"]) <= float(trade["sl"])
    except (KeyError, ValueError, TypeError):
        return False


def check_target_trigger(trade, price_bar):
    """
    Target triggered when HIGH >= target.
    B21: uses HIGH not close for target detection.
    """
    try:
        return float(price_bar["high"]) >= float(trade["target"])
    except (KeyError, ValueError, TypeError):
        return False


def check_partial_trigger(trade, price_bar):
    """
    Partial exit triggered when HIGH >= partial_tgt.
    B18/B21: uses HIGH not close. Only fires if no partial taken yet.
    """
    try:
        # Already partially closed — don't trigger again
        if int(float(trade.get("qty_closed", 0) or 0)) > 0:
            return False
        partial_tgt = float(trade.get("partial_tgt", 0) or 0)
        if partial_tgt <= 0:
            return False
        return float(price_bar["high"]) >= partial_tgt
    except (KeyError, ValueError, TypeError):
        return False


def is_day_cap(trade, today, hold_days=None):
    """Returns True if trade has been held >= HOLD_DAYS trading days."""
    days = _count_trading_days(trade.get("date", ""), today)
    cap  = hold_days or HOLD_DAYS
    return days >= cap


# ── P&L calculation ────────────────────────────────────────

def calc_final_pnl(trade, exit_price, exit_reason):
    """
    Calculate total P&L including any already-booked partial profit.
    B18: accounts for partial_pnl already realised.
    """
    try:
        entry      = float(trade.get("entry", 0) or 0)
        qty_open   = int(float(trade.get("qty_open", 0) or 0))
        partial_pnl= float(trade.get("partial_pnl", 0) or 0)
        remaining_pnl = qty_open * (float(exit_price) - entry)
        return round(partial_pnl + remaining_pnl, 2)
    except (ValueError, TypeError):
        return 0.0


# ── Process single trade ───────────────────────────────────

def process_trade(trade, price_bar, paper_trades_path=None, trade_date=None):
    """
    Check one open trade and apply: partial exit, SL, target, day cap.
    Updates trade dict in-place. Returns exit_reason or None.
    B18: partial exit automated here.
    """
    if trade_date is None:
        trade_date = datetime.now(IST).date()

    entry      = float(trade.get("entry", 0) or 0)
    qty_open   = int(float(trade.get("qty_open",  trade.get("qty", 0)) or 0))
    days       = _count_trading_days(trade.get("date", ""), trade_date)

    # ── Step 1: Partial exit (B18 fix) ────────────────────
    if check_partial_trigger(trade, price_bar):
        partial_tgt = float(trade.get("partial_tgt", 0))
        qty_to_close = qty_open // 2
        if qty_to_close > 0:
            partial_pnl = round(qty_to_close * (partial_tgt - entry), 2)
            trade["qty_closed"]        = qty_to_close
            trade["qty_open"]          = qty_open - qty_to_close
            trade["partial_exit_price"]= round(partial_tgt, 2)
            trade["partial_exit_date"] = price_bar["date"]
            trade["partial_pnl"]       = partial_pnl
            trade["sl"]                = round(entry, 2)  # move SL to breakeven
            trade["status"]            = "partial"
            print(f"  ◑ PARTIAL {trade['ticker'].replace('.NS','')} "
                  f"{qty_to_close}@{partial_tgt:.2f}  "
                  f"P&L so far: Rs{partial_pnl:+,.0f}  SL→breakeven")
            # Don't close yet — let remaining position run

    # ── Step 2: Full exit conditions ───────────────────────
    qty_remaining = int(float(trade.get("qty_open", 0) or 0))
    sl            = float(trade.get("sl", 0) or 0)

    exit_reason = None
    exit_price  = None

    if check_sl_trigger(trade, price_bar):
        exit_reason = "SL"
        exit_price  = sl                          # exit at SL price
    elif check_target_trigger(trade, price_bar):
        exit_reason = "TARGET"
        exit_price  = float(trade.get("target", 0))
    elif is_day_cap(trade, trade_date):
        exit_reason = "DAY_CAP"
        exit_price  = price_bar["close"]          # exit at close on day cap

    if exit_reason:
        total_pnl = calc_final_pnl(trade, exit_price, exit_reason)
        result    = "WIN" if total_pnl > 0 else "LOSS"
        trade.update({
            "status":      "closed",
            "exit_date":   price_bar["date"],
            "exit_price":  round(float(exit_price), 2),
            "exit_reason": exit_reason,
            "pnl":         total_pnl,
            "result":      result,
            "days_held":   days,
            "qty_open":    0,
        })
        icon = "✅" if result == "WIN" else "❌"
        print(f"  {icon} CLOSED {trade.get('id','')} "
              f"{trade['ticker'].replace('.NS','')} "
              f"{exit_reason} Rs{total_pnl:+,.0f}")

    return exit_reason


# ── Monitor all open trades ────────────────────────────────

def monitor_and_close(paper_trades_path=None, trade_log_path=None):
    """
    Check all open paper trades. Close when conditions met.
    Returns (closed_today, all_trades).
    """
    path      = paper_trades_path or PAPER_TRADES_FILE
    today     = datetime.now(IST).date()
    closed_today = []

    # Load ALL rows (open and closed) for rewrite
    all_rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            all_rows = list(csv.DictReader(f))

    open_trades = [
        r for r in all_rows
        if r.get("status", "").lower() in ("open", "partial")
        and r.get("ticker", "").strip()
        and _is_valid_date(r.get("date", ""))
    ]

    if not open_trades:
        print("  No open paper trades.")
        _save_all_trades(all_rows, path)
        return [], all_rows

    print(f"  Checking {len(open_trades)} open trades...")

    for trade in open_trades:
        ticker = trade["ticker"]
        price  = _fetch_price(ticker)
        if price is None:
            print(f"  Could not fetch {ticker} — skipping")
            continue

        # Update current_price and live_pnl for dashboard visibility
        try:
            entry_val = float(trade.get("entry", 0) or 0)
            qty_open  = int(float(trade.get("qty_open", trade.get("qty", 0)) or 0))
            ltp       = price["close"]
            trade["current_price"] = round(ltp, 2)
            trade["live_pnl"]      = round((ltp - entry_val) * qty_open, 2)
        except Exception:
            pass

        exit_reason = process_trade(trade, price, path, today)

        if exit_reason:
            closed_today.append(trade)
            _append_trade_log(trade, trade_log_path)

    _save_all_trades(all_rows, path)
    return closed_today, all_rows


def _is_valid_date(s):
    """Returns True if s is a valid YYYY-MM-DD date string."""
    try:
        date.fromisoformat(str(s).strip())
        return True
    except (ValueError, TypeError):
        return False


# ── Performance stats ──────────────────────────────────────

def _calc_stats(trades):
    closed = [t for t in trades if t.get("status") == "closed"]
    open_t = [t for t in trades if t.get("status") in ("open", "partial")]
    if not closed:
        return None, open_t

    wins   = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]
    pnls   = [float(t.get("pnl", 0) or 0) for t in closed]
    total  = sum(pnls)
    wr     = len(wins) / len(closed) * 100 if closed else 0

    win_sum  = sum(float(t["pnl"]) for t in wins if t.get("pnl"))
    loss_sum = abs(sum(float(t["pnl"]) for t in losses if t.get("pnl")))
    pf       = round(win_sum / loss_sum, 2) if loss_sum > 0 else 0

    equity = CAPITAL; peak = CAPITAL; mdd = 0
    for p in pnls:
        equity += p; peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak * 100)

    today_d     = datetime.now(IST).date()
    week_start  = today_d - timedelta(days=today_d.weekday())
    month_start = today_d.replace(day=1)

    week_pnl  = sum(float(t.get("pnl",0) or 0) for t in closed
                    if t.get("exit_date","") >= week_start.isoformat())
    month_pnl = sum(float(t.get("pnl",0) or 0) for t in closed
                    if t.get("exit_date","") >= month_start.isoformat())

    by_conf = {}
    for label in ["BUY", "WATCH"]:
        g = [t for t in closed if t.get("conf_label") == label]
        if g:
            w = len([t for t in g if t.get("result") == "WIN"])
            by_conf[label] = {
                "n":   len(g),
                "wr":  round(w / len(g) * 100, 1),
                "pnl": round(sum(float(t.get("pnl",0) or 0) for t in g), 0),
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

def build_scoreboard_message(closed_today, all_trades):
    now      = datetime.now(IST)
    date_str = now.strftime("%a %d %b · %I:%M %p IST").upper()
    stats, open_t = _calc_stats(all_trades)

    lines = [
        "<b>SCOREBOARD</b>",
        f"<i>{date_str}</i>",
        f"{'─'*32}",
    ]

    if closed_today:
        lines.append(f"<b>Closed today ({len(closed_today)})</b>")
        for t in closed_today:
            pnl  = float(t.get("pnl", 0) or 0)
            icon = "✅" if t.get("result") == "WIN" else "❌"
            rsn  = t.get("exit_reason", "")
            nm   = t.get("ticker", "").replace(".NS", "")
            cl   = t.get("conf_label", "")
            partial = float(t.get("partial_pnl", 0) or 0)
            partial_note = f"  (incl. partial Rs{partial:+,.0f})" if partial else ""
            lines.append(
                f"  {icon} {nm}  {rsn}  "
                f"<b>Rs {pnl:+,.0f}</b>  [{cl}]{partial_note}"
            )
    else:
        lines.append("No trades closed today.")

    if open_t:
        lines.append(f"{'─'*32}")
        lines.append(f"<b>Open trades ({len(open_t)})</b>")
        for t in open_t:
            nm    = t.get("ticker", "").replace(".NS", "")
            entry = float(t.get("entry", 0) or 0)
            sl    = float(t.get("sl", 0) or 0)
            today_d = datetime.now(IST).date()
            days  = _count_trading_days(t.get("date", ""), today_d)
            status= t.get("status", "open")
            # Show partial booked if exists
            partial_note = ""
            if status == "partial":
                partial_pnl = float(t.get("partial_pnl", 0) or 0)
                partial_note = f"  ◑ partial Rs{partial_pnl:+,.0f} booked"
            # SL trail indicator
            sl_tag = ""
            if sl >= entry + 0.01:
                sl_tag = "  🔒 SL→breakeven"
            # Show current price and live P&L if available
            ltp     = t.get("current_price", "")
            lpnl    = t.get("live_pnl", "")
            entry_v = float(t.get("entry", 0) or 0)
            if ltp and lpnl:
                ltp   = float(ltp)
                lpnl  = float(lpnl)
                arrow = "↑" if lpnl >= 0 else "↓"
                pct   = round((ltp - entry_v) / entry_v * 100, 1) if entry_v else 0
                lines.append(
                    f"  {nm}  Day {days}/{HOLD_DAYS}  "
                    f"{entry_v:,.0f}→{ltp:,.0f} ({arrow}{abs(pct):.1f}%)  "
                    f"Rs {lpnl:+,.0f}"
                    f"{sl_tag}{partial_note}"
                )
            else:
                lines.append(
                    f"  {nm}  Day {days}/{HOLD_DAYS}"
                    f"{sl_tag}{partial_note}"
                )

    if stats:
        lines += [
            f"{'─'*32}",
            f"<b>This week</b>   Rs {stats['week_pnl']:+,.0f}",
            f"<b>This month</b>  Rs {stats['month_pnl']:+,.0f}",
            f"<b>All time</b>    Rs {stats['total_pnl']:+,.0f}",
            f"{'─'*32}",
            f"Win rate  {stats['win_rate']:.0f}%  "
            f"({stats['wins']}W / {stats['losses']}L)",
            f"Profit factor  {stats['profit_factor']:.2f}x",
            f"Max drawdown   {stats['max_dd']:.1f}%",
        ]
        if stats["by_conf"]:
            lines.append(f"{'─'*32}")
            lines.append("<b>By signal type</b>")
            for label, s in stats["by_conf"].items():
                lines.append(
                    f"  {label:6s}  {s['n']} trades  "
                    f"WR {s['wr']:.0f}%  Rs {s['pnl']:+,.0f}"
                )
        n = stats["total_closed"]
        if n in (10, 20, 30, 50):
            lines.append(f"{'─'*32}")
            if n == 30:
                lines += [
                    "🎯 <b>30 trades complete!</b>",
                    "Is win rate above 55%? If yes → go live.",
                ]
            else:
                lines.append(f"🎯 {n} trades complete. Keep going.")
    else:
        lines += [f"{'─'*32}", "No closed trades yet."]

    lines += [f"{'─'*32}", "<i>Paper trading · Not SEBI advice</i>"]
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
        print(f"\n  {stats['total_closed']} closed | {stats['total_open']} open | "
              f"WR {stats['win_rate']:.0f}% | Month Rs{stats['month_pnl']:+,.0f}")
    print("\n  Done.")


if __name__ == "__main__":
    run()
