# DECISIONS.md — Trading Bot V6 N200c + Tiered Hold
# Claude reads this FIRST at the start of every session.
# Last updated: 2026-04-22

---

## CURRENT STRATEGY — V6 N200c + Tiered Hold (LIVE)

Backtest results (10 years, 2015-2026):

| Metric | N200c baseline | Tiered Hold (live) | Change |
|--------|---------------|-------------------|--------|
| Monthly avg | Rs 20,468 | Rs 20,669 | +Rs 201 |
| Win rate | 55.8% | 56.4% | +0.6pp |
| Annual return | 40.9% | 41.3% | +0.4pp |
| Max drawdown | 8.1% | 7.4% | -0.7pp |
| Profit factor | 1.39x | 1.40x | +0.01x |

Tiered hold beats N200c on all 4 metrics. This is the live bot foundation.
OE improvement: WR 66%→79%, avg P&L Rs +413→Rs +1,332 per trade.

---

## PARAMETERS — LOCKED (do not change without backtest)

| Parameter | Value | Reason |
|-----------|-------|--------|
| ATR_SL_MULT | 2.0 | Wider SL reduces noise stop-outs |
| ATR_TGT_MULT | 3.0 | RR math: 3.0/2.0 = 1.5 |
| ATR_PARTIAL_MULT | 2.0 | Partial at 2x ATR, SL→breakeven |
| MIN_RR | 1.5 | Enforced by ATR math |
| HOLD_DAYS | 8 | BUY signals — trading days |
| WATCH_HOLD_DAYS | 5 | WATCH signals — backtested, beats N200c |
| RISK_PER_TRADE | 6000 | Fixed fractional: 1% of Rs 6L |
| MAX_POSITION | 150000 | Hard cap per trade |
| MAX_DEPLOYED | 360000 | 60% of capital maximum |
| VIX_AVOID | 22 | Above → STAY IN CASH |
| VIX_REDUCE | 18 | Above → size_multiplier = 0.5 |
| OVERSOLD_RSI_MAX | 38 | V6: tightened from 50 |
| ADX_TREND_MIN | 18 | Structural filter |
| BUY_MIN_SCORE | 4 | Out of 7 factors |
| MONTHLY_LOSS_FLOOR | 30000 | Stops signals when month loss > Rs 30K |
| CONSEC_LOSS_LIMIT | 3 | 3 losses → size_multiplier = 0.5 |

---

## UNIVERSE — LOCKED (125 stocks as of 2026-04-22)

Exclusions from Nifty 200:
- PIRAMALENT.NS — delisted from Yahoo Finance (removed 2026-04-22)
- TATAMOTORS.NS — delisted from Yahoo Finance
- BHARTIARTL.NS — TELECOM sector, 29% WR
- APOLLOHOSP.NS, MAXHEALTH.NS — HOSPITAL sector, 41% WR
- IRFC.NS, RAILTEL.NS — PSU weak, 43-50% WR
- M&MFIN.NS, LICHSGFIN.NS — NBFC weak, 44-48% WR

Star performers: PFC (74% WR), KPITTECH (75% WR), NBCC (68%), HEROMOTOCO (66%)

---

## SECTOR PROXIES — LOCKED

| Sector | Proxy | Note |
|--------|-------|------|
| BANKING | ^NSEBANK | |
| IT | ^CNXIT | |
| PHARMA | ^CNXPHARMA | |
| AUTO | ^CNXAUTO | |
| FMCG | ^CNXFMCG | |
| METAL | ^CNXMETAL | |
| CAPITAL | ^CNXINFRA | |
| CHEMICAL | ^CNXFMCG | FIXED: was ^CNXINFRA |
| CONSUMER | ^CNXCONSUMP | FIXED: was ^CNXFMCG |
| ENERGY | ^CNXENERGY | |
| INFRA | ^CNXINFRA | |
| NBFC | ^CNXFIN | New sector |
| PSU | ^CNXPSE | New sector |

---

## ARCHITECTURE — LOCKED

```
config.py     → All parameters (single source of truth)
fetcher.py    → Downloads data. Returns dict. No writes.
analyzer.py   → Screens stocks. Returns picks. No writes.
brain.py      → Orchestrator. Writes signals.json only.
alert.py      → Reads signals.json. Writes paper_trades.csv. Sends Telegram.
scoreboard.py → Reads paper_trades.csv. Writes paper_trades.csv + trade_log.csv. Sends Telegram.
```

Hard boundaries:
- fetcher: no writes, no alerts
- analyzer: no writes, no fetching
- brain: no Telegram, no paper_trades.csv writes
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

- BUY: score 4-7/7 → hold 8 days, shown prominently in alert
- WATCH: score 0-3/7 → hold 5 days, shown with lower emphasis
- STAY IN CASH: VIX above 22 → no signals at all

Confidence factors (7 total):
1. Sector uptrend (sector index close > EMA20)
2. RR >= 1.5
3. EV >= 2.0%
4. Capital >= Rs 1,20,000
5+6. Setup quality: RSI_DIVERGENCE=2pts, TREND_PULLBACK/BP=1pt, OE=0pt
7. RVOL > 1.5 (volume above 20-day average)

---

## SIZING — LOCKED (fixed fractional)

```
qty     = RISK_PER_TRADE / (entry - sl)   → always Rs 6,000 risk
capital = qty * entry  (capped at Rs 1,50,000)
```

VIX reduce (18-22): qty halved
Consecutive losses (3+): qty halved via size_multiplier
Percentage sizing (15%/10%/5%) is REMOVED permanently.

---

## EXIT SYSTEM — LOCKED

| Trigger | Condition | Exit price |
|---------|-----------|------------|
| Partial | Daily HIGH >= entry + 2x ATR | partial_tgt |
| SL | Daily LOW <= sl | sl price |
| Target | Daily HIGH >= entry + 3x ATR | target price |
| DAY_CAP BUY | Days held >= 8 trading days | close |
| DAY_CAP WATCH | Days held >= 5 trading days | close |

After partial: 50% qty exits, SL moves to entry (breakeven), rest runs to target.

---

## PAPER TRADES SCHEMA (V6 — all fields required)

```
id, date, ticker, setup_type, conf_label, conf_score,
entry, sl, target, partial_tgt, rr, qty, qty_open, qty_closed,
capital, hold_days, ev_pct, reason, sector, status,
exit_date, exit_price, exit_reason,
partial_exit_price, partial_exit_date, partial_pnl,
pnl, result, days_held, current_price, live_pnl
```

- hold_days stored per trade row (BUY=8, WATCH=5)
- current_price and live_pnl updated by scoreboard daily
- Closed trades also written to trade_log.csv

---

## BUGS FIXED IN V6 REBUILD (2026-04-17)

| Bug | Fix |
|-----|-----|
| B1: Partial week candle | to_weekly() always strips last (incomplete) row |
| B3: No duplicate block | _open_tickers() reads paper_trades, blocks re-entry |
| B4: Consecutive loss rule | brain.get_size_multiplier() reads trade_log.csv |
| B5: Monthly floor | brain.is_floor_hit() reads trade_log.csv |
| B6: Wrong remains_free | calc_remains_free() subtracts open_trades capital |
| B7: Wrong sector proxies | CHEMICAL→CNXFMCG, CONSUMER→CNXCONSUMP |
| B8: CNXCONSUMP 404 | sector_uptrend(None) returns True safely |
| B10: IST timezone | get_today_ist() always IST, never date.today() |
| B11: No deployment warning | Alert warns when >60% capital deployed |
| B12: Missing partial schema | All partial fields in PAPER_FIELDS |
| B15: OE on midcaps | oe_allowed() gate: OE only for Nifty50 stocks |
| B16: Phantom trades | load_open_trades() validates entry_date format |
| B18: Partial not automated | process_trade() triggers on HIGH >= partial_tgt |
| B20: No signals validation | read_signals() validates schema, never crashes |
| B21: Wrong exit prices | HIGH for target/partial, LOW for SL |

---

## ENHANCEMENTS POST-REBUILD

| Date | Change | Impact |
|------|--------|--------|
| 2026-04-21 | current_price + live_pnl added to paper_trades | Scoreboard shows live P&L per trade |
| 2026-04-22 | Tiered hold: BUY=8, WATCH=5 days | Beats N200c on all 4 metrics (backtested) |
| 2026-04-22 | PIRAMALENT.NS removed | Delisted from Yahoo Finance |
| 2026-04-22 | Clean paper_trades reset | Fresh V6 baseline from Apr 20 onwards |

---

## WHAT IS NOT BUILT YET

| Enhancement | Gate | Notes |
|-------------|------|-------|
| Auto-calibration of SETUP_WIN_RATE | 50 closed trades | Updates EV priors from live data |
| Opportunity cost sizing (Kelly) | 30 live trades | Need live WR per setup first |
| LLM sentiment veto | 30 live trades | Never creates signals, only vetoes |
| Short selling via F&O | Phase 2 | Real gap in long-only system |
| Upstox API execution | Phase 3 | After system proven with real money |
| GitHub Pages dashboard | After 30 trades | Nice to have |

---

## DECISIONS THAT MUST NOT BE REVISITED

| Decision | Reason |
|----------|--------|
| VIX=22 threshold | Tested at 26 — worse. Locked. |
| No stock blacklisting | Data snooping. ADX handles dynamically. |
| No seasonal gates | Curve fitting. |
| No RS filter | Tested in V5 — net negative. Removed. |
| No hard deployment cap | Unbacktestable in ticker-first loop. |
| No time-stop (flat N days) | Solved by tiered hold. |
| No provisional partial week | Data integrity, no exceptions. |
| No custom sector metric | Sector indices already correct. |
| Fixed fractional sizing | Backtest-validated. Do not revert. |
| Swing only phase 1 | No intraday until 30 trades prove system. |
| No early exit on small losses | DAY_CAP 60% WR — trust the system. |

---

## PAPER TRADING STATUS

- Clean start: 2026-04-22
- Strategy: V6 N200c + Tiered Hold
- Current open: IOC (BUY/8d), DABUR (BUY/8d), CIPLA (BUY/8d),
               RELIANCE (BUY/8d), LUPIN (WATCH/5d), HEROMOTOCO (BUY/8d)
- Decision gate: after 30 closed trades, compare live WR to backtest 56.4%
- If within 5% → consider going live with real money
- Manual execution: Sravan allocates via Upstox, bot is signal engine + tracker

---

## LIVE TRADING PLAN (when ready)

Bot generates signals at 8 PM IST. Sravan:
1. Reads alert — picks highest confidence signals within available capital
2. Places orders at market open (9:15 AM IST)
3. Sets SL and target orders on Upstox
4. Monitors partial exit price alerts manually
5. Bot tracks everything via scoreboard automatically

Manual position sizing:
```
SL price:   use exactly as shown in alert — never change
Shares:     your_capital / entry_price
Risk:       shares × (entry - sl)
Partial:    sell half shares when price hits partial_tgt shown in alert
```

---

## HOW TO START EVERY SESSION

1. Read DECISIONS.md first
2. Search conversation history for prior decisions on the topic
3. One problem per session
4. Upload relevant files when code is involved
5. Write test cases before building
6. Run scenario tests before declaring any fix correct
7. Never confirm market facts without web search first
8. Check PIRAMALENT.NS is removed from config before any backtest run

---

## REPO STRUCTURE

```
config.py
fetcher.py
analyzer.py
brain.py
alert.py
scoreboard.py
backtest_tiered_hold.py      ← reference backtest
.github/workflows/bot.yml    ← ONLY this path (not bot.yml at root)
DECISIONS.md
requirements.txt
signals.json                 ← auto-generated
paper_trades.csv             ← auto-generated
trade_log.csv                ← auto-generated
.gitignore
```

Verify workflow path (Windows): `git ls-files | findstr yml`
Expected: `.github/workflows/bot.yml` — one line only.
