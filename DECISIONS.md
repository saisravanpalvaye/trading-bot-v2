# DECISIONS.md — Trading Bot V6 N200c
# Claude reads this FIRST at the start of every session.
# Last updated: 2026-04-17

---

## STRATEGY — LOCKED (V6 N200c)

Backtest results (10 years, 2015-2026):
- 3,930 trades · 55.8% WR · Rs 20,468/month avg
- Annual return: 40.9% · Max drawdown: 8.1%
- 10 out of 11 years profitable
- 2025 worst year: -Rs 1,56,797 (accepted risk)

V6 N200c is the live bot foundation. Do not change parameters without new live data.

---

## PARAMETERS — LOCKED (do not change without backtest)

| Parameter | Value | Reason |
|-----------|-------|--------|
| ATR_SL_MULT | 2.0 | Wider SL reduces noise stop-outs (SL hit rate 36% → 25%) |
| ATR_TGT_MULT | 3.0 | Forced by RR math: 3.0/2.0 = 1.5 = MIN_RR |
| ATR_PARTIAL_MULT | 2.0 | Partial exit at 2x ATR, SL moves to breakeven |
| MIN_RR | 1.5 | Minimum reward:risk enforced by ATR math |
| HOLD_DAYS | 8 | Trading days (not calendar). V4 was 6 — extended |
| RISK_PER_TRADE | 6000 | Fixed fractional: Rs 6,000 = 1% of Rs 6L capital |
| MAX_POSITION | 150000 | Rs 1,50,000 hard cap per trade (25% of capital) |
| MAX_DEPLOYED | 360000 | Rs 3,60,000 = 60% of capital maximum |
| VIX_AVOID | 22 | Above this → STAY IN CASH, zero signals |
| VIX_REDUCE | 18 | Above this → size_multiplier = 0.5 |
| OVERSOLD_RSI_MAX | 38 | V6: was 50 in old system — tighter gate |
| ADX_TREND_MIN | 18 | Structural filter — blocks whippy stocks |
| BUY_MIN_SCORE | 4 | Out of 7 factors. WATCH = score < 4 |
| MONTHLY_LOSS_FLOOR | 30000 | Rs 30,000 monthly loss stops new signals |
| CONSEC_LOSS_LIMIT | 3 | 3 consecutive losses → size_multiplier = 0.5 |

---

## UNIVERSE — LOCKED

- 126 Nifty 200 stocks (N200c watchlist)
- TELECOM excluded: BHARTIARTL removed (29% WR)
- HOSPITAL excluded: APOLLOHOSP, MAXHEALTH removed (41% WR)
- TATAMOTORS excluded: delisted from Yahoo Finance
- PSU weak removed: IRFC (50% WR), RAILTEL (43% WR)
- NBFC weak removed: M&MFIN (44% WR), LICHSGFIN (48% WR)
- New sectors added: NBFC (56% WR), PSU (66% WR)
- Star performers: PFC (71% WR), KPITTECH (75% WR), NBCC (68%)

---

## SECTOR PROXIES — LOCKED (fixed from old system)

| Sector | Proxy | Note |
|--------|-------|------|
| CHEMICAL | ^CNXFMCG | FIXED: was ^CNXINFRA — wrong |
| CONSUMER | ^CNXCONSUMP | FIXED: was ^CNXFMCG — wrong |
| NBFC | ^CNXFIN | New sector |
| PSU | ^CNXPSE | New sector |
| All others | Unchanged | Same as before |

---

## ARCHITECTURE — LOCKED

```
config.py    → All parameters (single source of truth)
fetcher.py   → Downloads data. Returns dict. No writes.
analyzer.py  → Screens stocks. Returns picks. No writes.
brain.py     → Orchestrator. Writes signals.json only.
alert.py     → Reads signals.json. Writes paper_trades.csv. Sends Telegram.
scoreboard.py→ Reads paper_trades.csv. Writes paper_trades.csv + trade_log.csv. Sends Telegram.
```

Hard boundaries (never cross):
- fetcher: no writes, no alerts
- analyzer: no writes, no fetching
- brain: no Telegram, no paper_trades.csv
- alert: no market data, no screener
- scoreboard: never touches signals.json
- morning: read-only, no mutations

---

## SCHEDULE — LOCKED

| Job | Cron (UTC) | IST | Days |
|-----|-----------|-----|------|
| brain + alert | 30 14 * * 0-4 | 8:00 PM | Sun–Thu |
| scoreboard | 5 10 * * 1-5 | 3:35 PM | Mon–Fri |
| morning reminder | 30 2 * * 1-5 | 8:00 AM | Mon–Fri |

---

## SIGNAL TIERS — LOCKED

- BUY: score 4-7/7 → shown prominently in alert
- WATCH: score 0-3/7 → shown with lower emphasis
- STAY IN CASH: VIX above 22 → no signals at all

Confidence factors (7 total):
1. Sector uptrend (close > EMA20 of sector index)
2. RR >= 1.5
3. EV >= 2.0%
4. Capital >= Rs 1,20,000 (large enough position)
5. Setup quality (RSI_DIVERGENCE=2pts, TREND_PULLBACK/BP=1pt)
6. (included in #5 — RSI_DIVERGENCE scores 2)
7. RVOL > 1.5 (volume above 20-day average)

---

## SIZING — LOCKED (fixed fractional)

Fixed fractional: Risk exactly Rs 6,000 per trade.
qty = RISK_PER_TRADE / (entry - sl)
cap = qty * entry (capped at MAX_POSITION = Rs 1,50,000)

VIX reduce (18-22): qty halved
Consecutive losses (3+): qty halved via size_multiplier

Old percentage sizing (15%/10%/5%) is REMOVED. Do not reintroduce.

---

## BUGS FIXED IN V6 REBUILD (2026-04-17)

| Bug | Fix |
|-----|-----|
| B1: Partial week in weekly detector | to_weekly() always strips last row (incomplete week) |
| B3: No dup block in live bot | _open_tickers() reads paper_trades, blocks already-open |
| B4: Consecutive loss rule not built | brain.get_size_multiplier() reads trade_log.csv |
| B5: Monthly floor not built | brain.is_floor_hit() reads trade_log.csv |
| B6: Wrong remains_free in alert | calc_remains_free() subtracts open_trades capital |
| B7: Wrong sector proxies | CHEMICAL→CNXFMCG, CONSUMER→CNXCONSUMP |
| B8: CNXCONSUMP 404 crash | sector_uptrend(None) returns True safely |
| B10: IST timezone | get_today_ist() and get_trade_date() always IST |
| B11: No deployment warning | Alert warns when >60% capital deployed |
| B12: Missing partial schema | All partial fields in PAPER_FIELDS |
| B15: OE on midcaps | oe_allowed() gate: OE only for Nifty50 stocks |
| B16: Phantom trades | load_open_trades() validates entry_date format |
| B18: Partial not automated | process_trade() triggers on high >= partial_tgt |
| B20: No signals.json validation | read_signals() validates schema, never crashes |
| B21: Wrong price for partial/SL | HIGH for target/partial, LOW for SL |

---

## WHAT IS NOT BUILT YET (Phase 2)

- LLM sentiment veto: locked until 30 live trades establish baseline
- Short selling via F&O futures: genuine phase 2 improvement
- Self-calibrating win rate priors: after 50 closed trades
- GitHub Pages monitoring dashboard
- Upstox API for live execution (phase 3)

---

## DECISIONS THAT MUST NOT BE REVISITED

- VIX=22 threshold: tested, 26 was worse — do not change
- No stock blacklisting by name: data snooping — let ADX filter handle it
- No seasonal gates (Jan/Feb bad months): curve fitting — do not add
- No RS filter: proved harmful in V5 (removed 54% WR trades) — do not re-add
- No position size cap (max 6 simultaneous): wrong in ticker-first backtest loop
- Fixed fractional over percentage sizing: backtest-validated — do not revert
- Swing only for phase 1: no intraday until 30 trades prove system

---

## PAPER TRADING STATUS

- Started: 2026-03-27
- Current strategy: V6 N200c (as of 2026-04-17 rebuild)
- Open trades from old system: preserved in paper_trades.csv
  (scoreboard continues tracking them until they close naturally)
- After 30 closed trades: review live WR vs backtest 55.8%
- Decision gate: if live WR within 5% of backtest → consider going live

---

## HOW TO START EVERY SESSION

1. Claude reads DECISIONS.md first
2. Check conversation search for any relevant prior decisions
3. One problem per session
4. Upload files if code is involved
5. Test cases before building — always
6. Scenario tests before declaring any fix correct — always

---

## REPO STRUCTURE (exactly these files)

```
config.py
fetcher.py
analyzer.py
brain.py
alert.py
scoreboard.py
.github/workflows/bot.yml   ← only this one, not bot.yml at root
DECISIONS.md
requirements.txt
signals.json                 ← auto-generated, tracked in git
paper_trades.csv             ← auto-generated, tracked in git
trade_log.csv                ← auto-generated, tracked in git
.gitignore
```

NOTE: Two bot.yml files exist in repo history. Only `.github/workflows/bot.yml`
is read by GitHub Actions. `bot.yml` at root is ignored. Verify with:
`git ls-files | grep yml`
