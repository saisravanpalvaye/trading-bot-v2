"""
intraday/analyst.py — ANALYST: Score, rank, and compute trade parameters.

Receives filtered candidates. Scores by RelVol. Pre-computes entry, SL, target.
Returns ranked list — highest conviction first.

You don't compute anything under pressure at 9:31 AM.
You read the ranked output and decide.
"""

from config import CAPITAL, RISK_PCT, RR, SLIPPAGE


def _compute_trade_params(c: dict, stop_mode: str = "midpoint") -> dict:
    """
    Compute entry, SL, target, qty, position_value for one stock.

    stop_mode:
      "midpoint" — SL at OR midpoint (tighter, more trades survive)
      "low"      — SL at OR low (wider, fewer trades stopped out)
    """
    or_high = c["or_high"]
    or_low  = c["or_low"]

    # Entry: OR high + slippage (realistic 15-min breakout fill)
    entry = or_high * (1 + SLIPPAGE)

    # Stop loss
    if stop_mode == "midpoint":
        sl_raw = (or_high + or_low) / 2
    else:  # "low"
        sl_raw = or_low

    sl = sl_raw * (1 - SLIPPAGE)   # slippage on stop exit too

    if entry <= sl:
        return {}  # degenerate setup — skip

    stop_distance = entry - sl
    risk_amt      = CAPITAL * RISK_PCT   # Rs 2,000

    # ATR-based position sizing: risk / stop_distance
    qty = max(1, int(risk_amt / stop_distance))

    # Target: entry + RR × stop_distance
    target = entry + RR * stop_distance

    position_value = qty * entry

    return {
        "entry":          round(entry, 2),
        "sl":             round(sl, 2),
        "target":         round(target, 2),
        "stop_distance":  round(stop_distance, 2),
        "qty":            qty,
        "risk_amt":       round(risk_amt, 2),
        "position_value": round(position_value, 2),
        "rr":             RR,
        "stop_mode":      stop_mode,
    }


def run(filtered: list[dict], stop_mode: str = "midpoint") -> list[dict]:
    """
    Score and rank filtered candidates by RelVol.
    Returns ranked list (highest RelVol first) with trade params attached.

    RelVol = OR candle volume / 20-day avg OR candle volume.
    Higher RelVol = more institutional participation = stronger breakout.
    """
    print(f"\n[ANALYST] Scoring {len(filtered)} candidates  (stop_mode={stop_mode})")
    scored = []

    for c in filtered:
        params = _compute_trade_params(c, stop_mode=stop_mode)
        if not params:
            print(f"[ANALYST] {c['symbol']:<14} SKIP — degenerate setup (entry <= sl)")
            continue

        rel_vol = c.get("rel_vol") or 1.0   # default 1.0 if vol avg unavailable

        entry = params["entry"]
        sl    = params["sl"]
        tgt   = params["target"]
        qty   = params["qty"]
        pv    = params["position_value"]

        result = {**c, **params, "score": rel_vol}
        scored.append(result)

        print(f"[ANALYST] {c['symbol']:<14} "
              f"entry={entry:.2f}  sl={sl:.2f}  tgt={tgt:.2f}  "
              f"qty={qty}  exposure=Rs{pv:,.0f}  RelVol={rel_vol:.2f}")

    # Rank by RelVol (conviction proxy)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    print(f"\n[ANALYST] Ranked output ({len(scored)} signals):")
    for i, s in enumerate(scored, 1):
        print(f"  #{i}  {s['symbol']:<14} RelVol={s.get('score',0):.2f}  "
              f"entry={s['entry']}  sl={s['sl']}  tgt={s['target']}")

    return scored
