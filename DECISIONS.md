# DECISIONS.md — Trading Bot v2
# Claude reads this FIRST at the start of every session.
# Last updated: 2026-03-25

---

## PROJECT BASICS
- Repo: NEW GitHub repo (not the old trading-bot)
- All files in ROOT of repo — no subdirectories
- Only one bot.yml: .github/workflows/bot.yml
- Capital: Rs 6,00,000 (paper trading for first 30 trades)
- Trader: Sravan Palvai, Dallas TX (UTC-5 / UTC-6)
- Telegram: Chat ID 5001387539

## SCHEDULE (LOCKED — do not change)
- Brain + Alert : `30 14 * * 0-4`  = 8:00 PM IST
- Morning reminder: `30 2 * * 1-5` = 8:00 AM IST
- Scoreboard    : `5 10 * * 1-5`   = 3:35 PM IST
- WHY 8 PM: market data is fresh (closed at 3:30 PM), no GitHub queue delay, Sravan gets alert at 8:30 AM Dallas time — 13 hours before market open

## SIGNAL TIERS (LOCKED)
- STRONG BUY: score 5-6/6 → size 15% = Rs 90,000
- BUY: score 3-4/6 → size 10% = Rs 60,000
- WATCH: score 0-2/6 → size 5% = Rs 30,000 (Sravan's call)
- STAY IN CASH: VIX above 22 → no signals at all

## KEY THRESHOLDS (LOCKED — do not change without backtest)
- VIX_AVOID = 22
- VIX_REDUCE = 18
- ADX_TREND_MIN = 18
- ATR_SL_MULT = 1.5
- ATR_TGT_MULT = 2.5
- MAX_HOLD_DAYS = 6 (trading days)
- MIN_RR = 1.5
- TREND_RSI_MIN = 52 | TREND_RSI_MAX = 66
- OVERSOLD_RSI_MAX = 50

## ARCHITECTURE DECISIONS (LOCKED)
- brain.py → writes signals.json → alert.py reads it (decoupled)
- alert.py auto-logs ALL signals to paper_trades.csv (Sravan does NOTHING)
- scoreboard.py runs independently — works even if brain failed
- config.py is the ONLY place any number lives
- No chart images — text alerts only (faster, never fails)
- No Upstox API — phase 1 is paper trading only
- No intraday — swing only until 30 trades prove the system

## PHASE 1 GOAL (30 days)
- Bot tracks itself completely automatically
- Sravan only reads 8 PM alert and 4 AM scoreboard
- After 30 closed trades: is win rate above 55%?
- If yes → consider going live with real money

## PHASE 2 (after 30 trades prove it)
- Sentiment analysis as veto layer (not signal creator)
- Intraday signals (separate format, separate schedule)
- Upstox API for live execution
- Dashboard on GitHub Pages

## FILES IN THIS REPO (exactly these, no others)
- config.py — all settings
- fetcher.py — data download
- analyzer.py — signal detection
- brain.py — orchestrator
- alert.py — Telegram + paper trade logger
- scoreboard.py — P&L tracker
- backtest.py — 10yr backtest
- .github/workflows/bot.yml — three jobs
- DECISIONS.md — this file
- .gitignore
- requirements.txt
- paper_trades.csv (auto-generated, tracked in git)
- signals.json (auto-generated, tracked in git)

## BACKTEST RESULTS (run 2026-03-25)
- 3,434 trades · 52.1% WR · Rs +7.46L total · Rs 6,090/month avg
- Max drawdown 4.2% — system is safe
- Best setup: RSI_DIVERGENCE 61% WR (only 90 trades/10yr — fires rarely)
- Best months: Aug, Nov, May, Jun (57-59% WR)
- Worst months: Feb (41% WR), Dec (47% WR)
- 2025 was a losing year (-Rs 3K/month avg) — market selloff, not system failure

## HONEST INCOME EXPECTATIONS
- Rs 6,090/month average on Rs 6L capital
- 62% of months are positive, 38% negative
- Worst single month: -Rs 56,284 (rare, happened once)
- Rs 30K/month requires Rs 25-30L capital — NOT a strategy tweak
- Path to Rs 30K: add Rs 20K/month from salary to capital pool
  - Year 1: Rs 9.4L capital → Rs 9,400/month
  - Year 2: Rs 14.2L capital → Rs 14,200/month
  - Year 3: Rs 20.2L capital → Rs 20,000/month

## DECISIONS MADE (do not revisit without new data)
- Swing only for phase 1 — no intraday until paper trading proves system
- No stock blacklisting based on backtest — that's data snooping
- No seasonal gates (Feb/Dec) — that's curve fitting
- No equity holding — these are swing entry signals, not buy-and-hold signals
- Focused 15 stocks NOT implemented — higher quality but LESS income (Rs 3,891 vs Rs 6,090)
- STRONG BUY sizing kept at Rs 90K for now — scoring formula needs live validation
- Full automation (Upstox API execution) is phase 3 — not phase 1 or 2

## LLM INTEGRATION PLAN (phase 2 — do not build until 30 live trades complete)
- Goal: news sentiment as VETO layer only — never creates signals, only blocks them
- How it works: analyzer finds 3 signals → LLM reads today's news for those 3 stocks → if negative news found, signal downgraded from BUY to WATCH
- Only call LLM on stocks that passed technical filter (3-5 calls/night, not 50)
- Cost: ~Rs 15-25/night using Claude API — negligible vs trading income
- News source: NSE announcements + Economic Times / Moneycontrol headlines
- New file: llm_context.py — sits between analyzer.py and alert.py
- What to measure: does win rate improve on signals the LLM did NOT veto vs baseline?
- DO NOT BUILD until 30 paper trades give us a baseline to compare against

## PHASE ROADMAP
- Phase 1 (now — 30 days): Paper trading, fully automatic, Sravan only reads alerts
- Phase 2 (after 30 trades): Review live results, add intraday signals, discuss full automation
- Phase 3 (after intraday proven): Upstox API integration, full execution automation
- Phase 4: Scale capital to Rs 20-30L for Rs 30K/month target

## PAPER TRADING STARTED
- Date: 2026-03-27 (first market day after setup)
- After 30 days: upload paper_trades.csv and scoreboard numbers
- Key question to answer: is live win rate close to 52%?
- If yes → go live. If no → investigate why before risking real money.

## HOW TO START EVERY SESSION
1. Say "continue from previous chat"
2. Claude reads this file first
3. One problem per session
4. Upload files if code is involved

## BUGS FIXED (2026-03-26 session)
- brain.py: was checking TODAY is market day — fixed to check TOMORROW
  (brain runs at 8 PM to prepare for next morning, so tomorrow is what matters)
- alert.py: was showing today's date in header — fixed to show tomorrow's date
  Format: "FRI 27 MAR 2026 · 11:52 PM IST  (for tomorrow's open)"
- Lesson: always run scenario tests before saying "working correctly"
  Scenarios to always test: holiday evening, Friday evening, Sunday evening, consecutive holidays

## HOW WE CAUGHT BUGS THIS SESSION
- Sravan spotted the date issue by thinking about intent, not code
- Rule going forward: Claude runs scenario tests and shows pass/fail output
  before declaring any file correct. No more "working perfectly" without proof.
- brain.py: trade_date was writing today's date — fixed to write next market day
  (skips weekends AND holidays, so Friday evening correctly writes Monday's date)
  Tested: Thu holiday→Fri27, Fri→Mon30, Sun→Mon30, Thu before long weekend→Mon+
- brain.py: added midnight rule — if running between 12 AM and 6 AM IST,
  treat today as trade date (handles GitHub Actions delays + manual test runs)
  Tested 8 scenarios all pass including Fri 12:08 AM → shows Fri 27 correctly

## BUGS FIXED (2026-03-27 session)
- fetcher.py: batch size reduced 8→4, delay 1.2→2.0 to fix yfinance duplicates
  (23/49 stocks were showing as duplicates — half the watchlist was wrong data)
- config.py: TATAMOTORS.NS removed — delisted from Yahoo Finance
- alert.py: confirmed reads trade_date from signals.json not recalculating
- brain.py: date.today() returns UTC on GitHub runners — fixed to now.date() (IST)
  Root cause: 01:26 AM IST = 7:56 PM UTC March 26 (holiday) → jumped to March 30
  Fix: use now.date() which uses the IST timezone we already set on `now`
  Lesson: NEVER use date.today() or datetime.now() without explicit timezone on GitHub Actions

## BUGS FIXED (2026-04-09 session)
- analyzer.py: `too many values to unpack (expected 6)` crash
  Root cause: `_quality_and_size()` failure path returned `False + 6 zeros = 7 values`
  but caller unpacked only 6. Fixed: `*([0] * 6)` → `*([0] * 5)` (False + 5 = 6 total)
  4 occurrences fixed.
- First day VIX dropped below 20 (19.7) — 8 signals fired successfully after fix.

## FEATURE ADDED (2026-04-09 session)
- scoreboard.py: Trailing Stop-Loss implemented
  Phase 1 — Breakeven: price >= entry + 2% → SL moved to entry (no loss possible)
  Phase 2 — Trail: price >= entry + 4% → SL trailed to today's low - 0.5% buffer
  Scoreboard message now shows 🔒 tag on trades where SL has been trailed
  Paper trades only — no impact on live bot or Upstox orders
  DECISIONS: trailing SL is intentional and locked. Do not remove without backtest.
