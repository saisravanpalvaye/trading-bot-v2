"""
intraday/executor.py — EXECUTOR: Obeys. Does not judge.

PAPER_MODE=True  → Logs "would trade" to decisions.csv. Prints to stdout.
                   Sends a Telegram tagged 📝 PAPER (scheduled runs only). No real orders.
PAPER_MODE=False → Sends ranked Telegram alert (top 1-2 by RelVol).
                   Phase 2: auto bracket order via Upstox API.

EXECUTOR has no veto. If RISK approved it, EXECUTOR executes.
"""

import requests
from datetime import datetime, timezone, timedelta
from config import (
    PAPER_MODE, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, RR,
)
import logger

IST = timezone(timedelta(hours=5, minutes=30))


def _send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, params={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=15)
        if r.status_code == 200:
            print(f"  [EXECUTOR] Telegram sent ✓")
            return True
        print(f"  [EXECUTOR] Telegram error {r.status_code}: {r.text[:120]}")
        return False
    except Exception as e:
        print(f"  [EXECUTOR] Telegram failed: {e}")
        return False


def notify(text: str, mode: str) -> None:
    """Plain status message (e.g. 'no trades today') for scheduled runs.
    Silent in paper_replay and when Telegram isn't configured."""
    if mode == "paper_replay" or not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return
    tag = "📝 PAPER — " if PAPER_MODE else ""
    _send_telegram(f"<b>{tag}ORB</b>  {text}")


def _format_alert(approved: list[dict]) -> str:
    """Format ranked signal list as HTML Telegram message."""
    now_ist = datetime.now(IST).strftime("%d %b %Y  %H:%M IST")
    tag = "📝 PAPER — " if PAPER_MODE else ""
    lines = [
        f"<b>{tag}🟢 ORB SIGNALS — {now_ist}</b>",
        f"<i>Top {len(approved)} by RelVol | Mode: LONG | 2:1 R:R | Exit: 15:20</i>",
        "",
    ]
    for i, s in enumerate(approved, 1):
        sym    = s["symbol"]
        entry  = s["entry"]
        sl     = s["sl"]
        tgt    = s["target"]
        qty    = s["qty"]
        rv     = s.get("rel_vol", "?")
        pv     = s["position_value"]
        risk   = s["risk_amt"]
        lines += [
            f"<b>#{i} {sym}</b>  |  RelVol: <b>{rv:.2f}</b>",
            f"  Entry: <b>Rs {entry:.2f}</b>  (buy above OR high on breakout)",
            f"  SL:    Rs {sl:.2f}  ({s.get('stop_mode','midpoint')} stop)",
            f"  Target: Rs {tgt:.2f}  (RR {RR}:1)",
            f"  Qty:   {qty} shares  |  Exposure: Rs {pv:,.0f}  |  Max loss: Rs {risk:,.0f}",
            f"  Gap: {s.get('gap_pct',0):.2f}%  |  OR width: {s.get('or_width_pct',0):.2f}%",
            "",
        ]
    lines.append("📝 Paper trade — track it, don't place it." if PAPER_MODE
                 else "⚠ Bracket order in Upstox app. Manual confirmation required.")
    return "\n".join(lines)


def run(approved: list[dict], mode: str = "market_open") -> None:
    """
    Execute approved signals.

    Paper mode: log each as TRADE decision, print to stdout.
    Live mode:  send Telegram alert (top 2 by RelVol).
    """
    if not approved:
        print("[EXECUTOR] No approved signals — nothing to execute")
        return

    print(f"\n[EXECUTOR] {'PAPER MODE' if PAPER_MODE else 'LIVE MODE'} — "
          f"{len(approved)} signal(s)")

    for s in approved:
        sym = s["symbol"]
        logger.log(sym, "EXECUTOR", "TRADE", "paper_trade" if PAPER_MODE else "live_alert",
                   mode=mode,
                   entry=s["entry"], sl=s["sl"], target=s["target"],
                   qty=s["qty"], position_value=s["position_value"],
                   risk_amt=s["risk_amt"], rel_vol=s.get("rel_vol",""),
                   gap_pct=s.get("gap_pct",""), or_width_pct=s.get("or_width_pct",""),
                   nifty_ok=s.get("nifty_ok",""), trend_ok=s.get("trend_ok",""))

    if PAPER_MODE:
        print("\n" + "="*60)
        print("  PAPER TRADES — Would execute:")
        print("="*60)
        for i, s in enumerate(approved, 1):
            print(f"  #{i} {s['symbol']:<14}  "
                  f"entry={s['entry']}  sl={s['sl']}  tgt={s['target']}  "
                  f"qty={s['qty']}  exposure=Rs{s['position_value']:,.0f}  "
                  f"RelVol={s.get('rel_vol','?'):.2f}")
        print("="*60)
        # Scheduled paper runs still alert (tagged PAPER) so automation is visible
        if mode != "paper_replay" and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            _send_telegram(_format_alert(approved[:2]))
        else:
            print("  Telegram not sent (replay mode or TELEGRAM_* not set in .env)\n")
        return

    # Live mode: send top 2 to Telegram
    top2    = approved[:2]
    message = _format_alert(top2)
    success = _send_telegram(message)
    if success:
        print(f"[EXECUTOR] Alert sent for: {', '.join(s['symbol'] for s in top2)}")
    else:
        print("[EXECUTOR] Telegram failed — check TELEGRAM_TOKEN and TELEGRAM_CHAT_ID")
