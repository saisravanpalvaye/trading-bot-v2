"""
intraday/risk.py — RISK: Position-level and portfolio-level gates.

Runs AFTER ANALYST. Final gate before EXECUTOR.
No signal reaches EXECUTOR without passing RISK.

RISK has no opinion on setups. It only enforces rules.
"The desk looks good" is not a RISK input.
"""

from config import (
    CAPITAL, MAX_OPEN_POSITIONS, MAX_POSITION_VALUE,
    RISK_PCT, CONSEC_LOSS_TRIGGER, CONSEC_LOSS_RISK_PCT,
    DECISIONS_FILE,
)
import logger
import csv
from pathlib import Path


def _count_today_trades(mode: str) -> int:
    """Count trades already taken today (from decisions log)."""
    return logger.today_trade_count()


def _consecutive_losses() -> int:
    """
    Count consecutive KILL/loss trades at end of decisions log.
    Used for half-sizing after N consecutive losses.
    """
    if not DECISIONS_FILE.exists():
        return 0
    rows = []
    with open(DECISIONS_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("decision") in ("TRADE", "LOSS"):
                rows.append(row)
    if not rows:
        return 0

    count = 0
    for row in reversed(rows):
        if row.get("pnl_est", "") and float(row.get("pnl_est", 0) or 0) < 0:
            count += 1
        elif row.get("decision") == "TRADE":
            break  # hit a trade with no PnL recorded — stop counting
        else:
            break
    return count


def apply(ranked: list[dict], mode: str = "market_open") -> list[dict]:
    """
    Apply portfolio and position caps to ranked ANALYST output.
    Returns approved signals (up to MAX_OPEN_POSITIONS), with final qty.

    Rules enforced:
      1. MAX_OPEN_POSITIONS: cap total trades today
      2. MAX_POSITION_VALUE: cap single-trade exposure
      3. Consecutive-loss half-sizing: reduce risk_pct after trigger
    """
    print(f"\n[RISK] Applying portfolio gates")

    today_trades = _count_today_trades(mode)
    slots_left   = MAX_OPEN_POSITIONS - today_trades
    consec_losses = _consecutive_losses()

    # Consecutive-loss guard
    effective_risk_pct = RISK_PCT
    if consec_losses >= CONSEC_LOSS_TRIGGER:
        effective_risk_pct = CONSEC_LOSS_RISK_PCT
        print(f"[RISK] ⚠ {consec_losses} consecutive losses — half-sizing active "
              f"(risk {effective_risk_pct*100:.1f}% vs normal {RISK_PCT*100:.1f}%)")

    print(f"[RISK] Slots today: {slots_left}/{MAX_OPEN_POSITIONS}  "
          f"Consec losses: {consec_losses}  "
          f"Effective risk: {effective_risk_pct*100:.1f}%")

    if slots_left <= 0:
        print(f"[RISK] MAX_OPEN_POSITIONS={MAX_OPEN_POSITIONS} reached — no new trades today")
        for s in ranked:
            logger.log(s["symbol"], "RISK", "KILL",
                       f"daily cap reached ({MAX_OPEN_POSITIONS} trades)", mode=mode)
        return []

    approved = []
    for s in ranked:
        if len(approved) >= slots_left:
            logger.log(s["symbol"], "RISK", "KILL",
                       f"daily cap reached ({MAX_OPEN_POSITIONS} trades)", mode=mode)
            continue

        sym = s["symbol"]

        # Recompute qty with effective risk_pct (may differ from ANALYST's)
        stop_distance = s["stop_distance"]
        risk_amt      = CAPITAL * effective_risk_pct
        qty           = max(1, int(risk_amt / stop_distance))
        position_value = qty * s["entry"]

        # Position value cap
        if position_value > MAX_POSITION_VALUE:
            qty            = max(1, int(MAX_POSITION_VALUE / s["entry"]))
            position_value = qty * s["entry"]
            print(f"[RISK] {sym:<14} qty capped: position_value would exceed "
                  f"Rs {MAX_POSITION_VALUE:,.0f} — reduced to qty={qty}")

        approved_signal = {
            **s,
            "qty":            qty,
            "risk_amt":       round(risk_amt, 2),
            "position_value": round(position_value, 2),
        }
        approved.append(approved_signal)

        print(f"[RISK] {sym:<14} APPROVED — qty={qty}  "
              f"exposure=Rs{position_value:,.0f}  "
              f"risk=Rs{risk_amt:,.0f}")
        logger.log(sym, "RISK", "PASS", "approved", mode=mode,
                   entry=s["entry"], sl=s["sl"], target=s["target"],
                   qty=qty, position_value=round(position_value,2),
                   risk_amt=round(risk_amt,2), rel_vol=s.get("rel_vol",""))

    print(f"[RISK] {len(approved)} signals approved for execution\n")
    return approved
